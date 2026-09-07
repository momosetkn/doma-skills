package example.entity

import org.seasar.doma.Column
import org.seasar.doma.Entity
import org.seasar.doma.Id
import org.seasar.doma.Metamodel
import org.seasar.doma.Table

/** Customers */
@Entity(metamodel = Metamodel())
@Table(catalog = "fixture_catalog", name = "customer")
class Customer {

    /** Customer ID */
    @Id
    @Column(name = "customer_id")
    var customerId: Long = -1L

    /** Synchronization note */
    @Column(name = "sync_note")
    var syncNote: String? = null
}
