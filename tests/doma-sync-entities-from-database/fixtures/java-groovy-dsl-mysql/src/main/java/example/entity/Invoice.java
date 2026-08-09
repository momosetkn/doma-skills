package example.entity;

import example.domain.Money;
import org.seasar.doma.Column;
import org.seasar.doma.Entity;
import org.seasar.doma.Id;
import org.seasar.doma.Table;

/** Invoices */
@Entity
@Table(catalog = "fixture_catalog", name = "invoice")
public class Invoice {

    /** Invoice ID */
    @Id
    @Column(name = "invoice_id")
    Long invoiceId;

// HANDWRITTEN-BEGIN:domain-property
    /** Total amount */
    @Column(name = "amount")
    Money amount;
// HANDWRITTEN-END:domain-property

    /** Returns the invoiceId. */
    public Long getInvoiceId() {
        return invoiceId;
    }

    /** Sets the invoiceId. */
    public void setInvoiceId(Long invoiceId) {
        this.invoiceId = invoiceId;
    }

    /** Returns the amount. */
    public Money getAmount() {
        return amount;
    }

    /** Sets the amount. */
    public void setAmount(Money amount) {
        this.amount = amount;
    }
}
