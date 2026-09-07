package example.entity;

import java.time.LocalDate;
import org.seasar.doma.Column;
import org.seasar.doma.Entity;
import org.seasar.doma.GeneratedValue;
import org.seasar.doma.GenerationType;
import org.seasar.doma.Id;
import org.seasar.doma.Metamodel;
import org.seasar.doma.Table;
import org.seasar.doma.Version;

/**
 */
@Entity(metamodel = @Metamodel)
@Table(schema = "public", name = "employee")
public class Employee {

    /** */
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "employee_id")
    Integer id;

    /** */
    @Column(name = "hire_date")
    LocalDate hireDate;

    /** */
    @Version
    @Column(name = "version")
    Integer version;

    /**
     * Returns the id.
     *
     * @return the id
     */
    public Integer getId() {
        return id;
    }

    /**
     * Sets the id.
     *
     * @param id the id
     */
    public void setId(Integer id) {
        this.id = id;
    }

    /**
     * Returns the hireDate.
     *
     * @return the hireDate
     */
    public LocalDate getHireDate() {
        return hireDate;
    }

    /**
     * Sets the hireDate.
     *
     * @param hireDate the hireDate
     */
    public void setHireDate(LocalDate hireDate) {
        this.hireDate = hireDate;
    }

    /**
     * Returns the version.
     *
     * @return the version
     */
    public Integer getVersion() {
        return version;
    }

    /**
     * Sets the version.
     *
     * @param version the version
     */
    public void setVersion(Integer version) {
        this.version = version;
    }
}
